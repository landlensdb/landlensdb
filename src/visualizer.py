class Visualize:
    """ """

    def __init__(self, data):
        self.data = data

    def popup_html(self, row):
        """
        Creates html
        """
        image = self.data.id[row]
        seq = self.data.seq[row]
        cam = self.data.camera_type[row]
        img = self.data.image_url[row]

        left_col_color = "#3e95b5"
        right_col_color = "#f2f9ff"

        html = (
            """
            <!DOCTYPE html>
            <html>
            <center> <table style="height: 126px; width: 305px;">
            <tbody>
            <tr>
            <td style="background-color: """
            + left_col_color
            + """;"><span style="color: #ffffff;">Image </span></td>
            <td style="width: 200px; padding-left: 5px; background-color: """
            + right_col_color
            + """;">{}</td>""".format(image)
            + """
            </tr>
            <tr>
            <td style="background-color: """
            + left_col_color
            + """;"><span style="color: #ffffff;">Sequence </span></td>
            <td style="width: 200px; padding-left: 5px; background-color: """
            + right_col_color
            + """;">{}</td>""".format(seq)
            + """
            </tr>
            <tr>
            <td style="background-color: """
            + left_col_color
            + """;"><span style="color: #ffffff;">Camera </span></td>
            <td style="width: 200px; padding-left: 5px; background-color: """
            + right_col_color
            + """;">{}</td>""".format(cam)
            + """
            </tr>
            </tbody>
            </table></center>
            <center><img src=\""""
            + img
            + """\" alt="thumbnail" width=305 ></center>
            </html>
            """
        )
        return html
