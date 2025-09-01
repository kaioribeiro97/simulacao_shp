import streamlit as st
import geopandas as gpd
import wntr
import os
import tempfile
import zipfile

def convert_shp_to_inp(zip_nodes_path, zip_links_path):
    """
    Converte shapefiles de nós e trechos para um arquivo EPANET .inp,
    aplicando as conversões de unidades necessárias.

    Args:
        zip_nodes_path (str): Caminho para o arquivo zip contendo o shapefile dos nós.
        zip_links_path (str): Caminho para o arquivo zip contendo o shapefile dos trechos.

    Returns:
        str: O conteúdo do arquivo .inp gerado como uma string.
    """
    try:
        # Cria diretórios temporários para extrair os arquivos
        with tempfile.TemporaryDirectory() as temp_dir_nodes, tempfile.TemporaryDirectory() as temp_dir_links:
            # Extrai os arquivos ZIP
            with zipfile.ZipFile(zip_nodes_path, 'r') as zip_ref:
                zip_ref.extractall(temp_dir_nodes)
            with zipfile.ZipFile(zip_links_path, 'r') as zip_ref:
                zip_ref.extractall(temp_dir_links)

            # Encontra os arquivos .shp dentro dos diretórios extraídos
            shapefile_nodes = next((os.path.join(temp_dir_nodes, f) for f in os.listdir(temp_dir_nodes) if f.endswith('.shp')), None)
            shapefile_links = next((os.path.join(temp_dir_links, f) for f in os.listdir(temp_dir_links) if f.endswith('.shp')), None)

            if not shapefile_nodes or not shapefile_links:
                raise FileNotFoundError("Não foi possível encontrar o arquivo .shp dentro de um dos arquivos ZIP.")

            # Leitura dos shapefiles
            nodes_gdf = gpd.read_file(shapefile_nodes)
            links_gdf = gpd.read_file(shapefile_links)

            # Inicializa a rede EPANET
            wn = wntr.network.WaterNetworkModel()

            # Dicionário para armazenar os nós
            nodes_dict = {}

            # Adiciona os nós a partir das coordenadas dos trechos
            for _, row in links_gdf.iterrows():
                start_point = row.geometry.coords[0]
                end_point = row.geometry.coords[-1]

                start_coords = (round(start_point[0], 6), round(start_point[1], 6))
                end_coords = (round(end_point[0], 6), round(end_point[1], 6))

                if start_coords not in nodes_dict:
                    node_id = f"N{len(nodes_dict) + 1}"
                    nodes_dict[start_coords] = node_id
                    wn.add_junction(node_id, base_demand=0, elevation=0, coordinates=start_coords)

                if end_coords not in nodes_dict:
                    node_id = f"N{len(nodes_dict) + 1}"
                    nodes_dict[end_coords] = node_id
                    wn.add_junction(node_id, base_demand=0, elevation=0, coordinates=end_coords)

            # Validação das colunas necessárias nos nós
            required_node_cols = {'Cota', 'Demanda'}
            if not required_node_cols.issubset(nodes_gdf.columns):
                 raise ValueError(f"O shapefile de nós deve conter as colunas: {', '.join(required_node_cols)}")

            # Atualiza os nós com elevação e demanda, aplicando conversões
            for _, row in nodes_gdf.iterrows():
                coords = (round(row.geometry.x, 6), round(row.geometry.y, 6))
                node_id = nodes_dict.get(coords)
                if node_id:
                    junction = wn.get_node(node_id)
                    # Conversão de pés para metros
                    junction.elevation = row['Cota'] / 3.280839895054167
                    # Conversão de GPM para LPS
                    junction.demand_timeseries_list[0].base_value = row['Demanda'] / 15850.32314147994

            # Validação das colunas necessárias nos trechos
            required_link_cols = {'diameter', 'Shape__Len', 'rugosidade'}
            if not required_link_cols.issubset(links_gdf.columns):
                 raise ValueError(f"O shapefile de trechos deve conter as colunas: {', '.join(required_link_cols)}")

            # Adiciona as ligações (trechos), aplicando conversões
            for _, row in links_gdf.iterrows():
                start_point = row.geometry.coords[0]
                end_point = row.geometry.coords[-1]

                start_coords = (round(start_point[0], 6), round(start_point[1], 6))
                end_coords = (round(end_point[0], 6), round(end_point[1], 6))

                node1 = nodes_dict[start_coords]
                node2 = nodes_dict[end_coords]
                link_id = f"P{len(wn.links) + 1}"

                # Converte diâmetro de polegadas para metros
                diameter_m = row['diameter'] / 39.37007874
                # Converte comprimento de pés para metros
                length_m = row['Shape__Len'] / 3.280839895032449

                wn.add_pipe(link_id, node1, node2,
                            length=length_m,
                            diameter=diameter_m,
                            roughness=row['rugosidade'],
                            minor_loss=0.0)

            # Salva a rede em um arquivo .inp temporário
            with tempfile.NamedTemporaryFile(delete=False, mode='w+', suffix='.inp', encoding='utf-8') as temp_inp_file:
                output_inp_path = temp_inp_file.name
                wntr.network.write_inpfile(wn, output_inp_path)

            # Ajusta o arquivo .inp para garantir as unidades corretas
            with open(output_inp_path, 'r', encoding='utf-8') as file:
                data = file.readlines()

            options_index = -1
            clean_data = []
            # Procura por [OPTIONS] e remove linhas de unidades existentes para evitar duplicatas
            for line in data:
                 stripped_line = line.strip().upper()
                 if stripped_line == '[OPTIONS]':
                      options_index = len(clean_data)
                 elif stripped_line.startswith(('UNITS', 'FLOWUNITS', 'HEADLOSS')):
                      continue # Pula a linha
                 clean_data.append(line)

            # Se [OPTIONS] foi encontrado, insere as unidades corretas
            if options_index != -1:
                options = [
                    'Units               LPS\n',
                    'FlowUnits           LPS\n',
                    'Headloss            H-W\n'
                ]
                clean_data[options_index+1:options_index+1] = options

            # Junta as linhas em uma única string
            final_inp_content = "".join(clean_data)
            os.remove(output_inp_path) # Limpa o arquivo temporário
            return final_inp_content

    except Exception as e:
        st.error(f"Ocorreu um erro: {e}")
        return None

# --- Interface do Streamlit ---
st.set_page_config(page_title="Conversor SHP para INP", layout="wide")

st.title("Conversor de Shapefile para EPANET (.inp)")
st.markdown("""
Esta ferramenta converte arquivos Shapefile de uma rede de distribuição de água (nós e trechos)
em um arquivo de modelo EPANET (.inp).

**Instruções:**
1.  Compacte os arquivos do seu shapefile de **Nós** (incluindo `.shp`, `.shx`, `.dbf`, etc.) em um único arquivo `.zip`.
2.  Faça o mesmo para os arquivos do seu shapefile de **Trechos/Linhas**.
3.  Faça o upload dos dois arquivos `.zip` nos campos abaixo.
4.  Clique em "Converter para .inp".
5.  Se a conversão for bem-sucedida, um botão de download para o arquivo `.inp` aparecerá.
""")

st.sidebar.header("Upload dos Arquivos")

# File Uploader para os nós
uploaded_nodes = st.sidebar.file_uploader(
    "1. Upload do .zip do Shapefile de Nós",
    type=['zip'],
    help="O shapefile de nós deve conter as colunas: `Cota` (elevação) e `Demanda`."
)

# File Uploader para os trechos/links
uploaded_links = st.sidebar.file_uploader(
    "2. Upload do .zip do Shapefile de Trechos",
    type=['zip'],
    help="O shapefile de trechos deve conter as colunas: `diameter` (diâmetro), `Shape__Len` (comprimento) e `rugosidade`."
)

if st.sidebar.button("Converter para .inp", type="primary"):
    if uploaded_nodes is not None and uploaded_links is not None:
        with st.spinner('Processando os arquivos e gerando o modelo...'):
            # Passa os objetos de arquivo diretamente para a função
            inp_data = convert_shp_to_inp(uploaded_nodes, uploaded_links)

        if inp_data:
            st.session_state['inp_data'] = inp_data
            st.session_state['conversion_done'] = True
            st.success("Conversão concluída com sucesso!")
        else:
            # Garante que o botão de download antigo não apareça se a nova conversão falhar
            st.session_state['conversion_done'] = False
    else:
        st.sidebar.warning("Por favor, faça o upload de ambos os arquivos .zip.")

# Exibe o botão de download se a conversão foi feita
if 'conversion_done' in st.session_state and st.session_state['conversion_done']:
    st.header("Download do Arquivo Gerado")
    st.download_button(
        label="Baixar Arquivo .inp",
        data=st.session_state['inp_data'],
        file_name="modelo_convertido.inp",
        mime="text/plain"
    )

    st.subheader("Pré-visualização do Arquivo .inp")
    st.text_area("Conteúdo do .inp", st.session_state['inp_data'], height=400)

